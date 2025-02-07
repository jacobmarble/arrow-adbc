// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"text/template"

	"golang.org/x/tools/go/packages"
)

const Ext = ".tmpl"

func formatSource(in []byte) ([]byte, error) {
	r := bytes.NewReader(in)
	cmd := exec.Command("goimports")
	cmd.Stdin = r
	out, err := cmd.Output()
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return nil, fmt.Errorf("error running goimports: %s", string(ee.Stderr))
		}
		return nil, fmt.Errorf("error running goimports: %s", string(out))
	}

	return out, nil
}

func formatCSource(in []byte) ([]byte, error) {
	r := bytes.NewReader(in)
	cmd := exec.Command("clang-format")
	cmd.Stdin = r
	out, err := cmd.Output()
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return nil, fmt.Errorf("error running clang-format: %s", string(ee.Stderr))
		}
		return nil, fmt.Errorf("error running clang-format: %s", string(out))
	}

	return out, nil
}

type pathSpec struct {
	in, out string
}

func (p *pathSpec) String() string { return p.in + " → " + p.out }
func (p *pathSpec) IsGoFile() bool { return filepath.Ext(p.out) == ".go" }
func (p *pathSpec) IsCFile() bool  { return filepath.Ext(p.out) == ".c" || filepath.Ext(p.out) == ".h" }

type tmplData struct {
	Driver string
	Prefix string
}

var fileList = []string{
	"driver.go.tmpl", "utils.c.tmpl", "utils.h.tmpl",
}

func main() {
	var (
		prefix     = flag.String("prefix", "", "function prefix")
		driverPkg  = flag.String("driver", "", "path to driver package")
		driverType = flag.String("type", "Driver", "name of the driver type")
		outDir     = flag.String("o", "", "output directory")
		tmplDir    = flag.String("in", "./_tmpl", "template directory [default=./_tmpl]")
	)

	flag.Parse()
	switch {
	case *prefix == "":
		log.Fatal("prefix is required")
	case *driverPkg == "":
		log.Fatal("driver pkg path is required")
	case *outDir == "":
		log.Fatal("must provide output directory with -o")
	}

	pkg, err := packages.Load(&packages.Config{
		Mode: packages.NeedName | packages.NeedTypes | packages.NeedModule,
		Dir:  *driverPkg,
	})
	if err != nil {
		log.Fatal(err)
	}

	switch len(pkg) {
	case 0:
		log.Fatalf("package %s not found", *driverPkg)
	case 1:
	default:
		log.Fatalf("more than one package met path %s", *driverPkg)
	}

	specs := make([]pathSpec, len(fileList))
	for i, f := range fileList {
		specs[i] = pathSpec{
			in:  filepath.Join(*tmplDir, f),
			out: filepath.Join(*outDir, strings.TrimSuffix(f, Ext))}
	}

	process(tmplData{Driver: pkg[0].Name + "." + *driverType, Prefix: *prefix}, specs)
}

func mustReadAll(path string) []byte {
	data, err := ioutil.ReadFile(path)
	if err != nil {
		log.Fatal(err)
	}

	return data
}

func fileMode(path string) os.FileMode {
	stat, err := os.Stat(path)
	if err != nil {
		log.Fatal(err)
	}
	return stat.Mode()
}

type formatter func([]byte) ([]byte, error)

func process(data interface{}, specs []pathSpec) {
	for _, spec := range specs {
		t, err := template.New("gen").Parse(string(mustReadAll(spec.in)))
		if err != nil {
			log.Fatalf("error processing template '%s': %s", spec.in, err)
		}

		var buf bytes.Buffer
		// preamble
		fmt.Fprintf(&buf, "// Code generated by %s. DO NOT EDIT.\n", spec.in)
		fmt.Fprintln(&buf)
		if err = t.Execute(&buf, data); err != nil {
			log.Fatalf("error executing template '%s': %s", spec.in, err)
		}

		generated := buf.Bytes()
		var f formatter
		if spec.IsGoFile() {
			f = formatSource
		} else if spec.IsCFile() {
			f = formatCSource
		}

		if f != nil {
			generated, err = f(generated)
			if err != nil {
				log.Fatalf("error formatting '%s': %s", spec.in, err)
			}
		}
		if err := ioutil.WriteFile(spec.out, generated, fileMode(spec.in)); err != nil {
			log.Fatal(err)
		}
	}
}
